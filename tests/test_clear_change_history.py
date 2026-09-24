# SPDX-License-Identifier: AGPL-3.0-or-later
"""``clear_change_history`` (Phase 147, ISS-177): refuses by default, truncates
every pghistory event table when explicitly told this is a golden build.

Two invariants, each with its own test:

* Without ``--golden-build`` the command raises ``CommandError`` and touches
  nothing -- on a real deployment the change history it would delete is the
  record `core/history.py` exists to keep.
* With ``--golden-build`` every event row a tracked model's save produced is
  gone afterward, and the tracked row itself -- and its current values -- are
  completely untouched. ``geography.Zone`` is used as the tracked model
  because it needs no more than a boundary to construct (``tests/factories.py``
  already has both), unlike most of the 41 tracked models this phase adds.
"""
import uuid

import pghistory
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

import pghistory.models as pghistory_models
from geography.models import Zone, ZoneEvent

from .factories import ZoneFactory


@pytest.mark.django_db
def test_refuses_without_the_golden_build_flag():
    """The default is refusal, and refusal must not truncate anything."""
    zone = ZoneFactory()
    assert ZoneEvent.objects.filter(pgh_obj_id=zone.id).count() == 1

    with pytest.raises(CommandError, match="--golden-build"):
        call_command("clear_change_history")

    # Untouched: the refusal happened before any TRUNCATE ran.
    assert ZoneEvent.objects.filter(pgh_obj_id=zone.id).count() == 1


@pytest.mark.django_db
def test_golden_build_clears_every_event_and_leaves_the_tracked_row_alone():
    # Wrapped in an explicit context (the same mechanism `manage.py` opens
    # around a real command, `core/history.py::command_context`) so this test
    # exercises pghistory_context too -- a bare save outside any open context
    # still writes its event row, but leaves no context row for the trigger
    # to point at, and that half of the truncate would go unverified.
    with pghistory.context(command="test"):
        zone = ZoneFactory(name="Pre-Clear Zone")
    zone_id = zone.id

    # Exactly one event: the insert `track_changes` records on create.
    assert ZoneEvent.objects.filter(pgh_obj_id=zone_id).count() == 1
    assert pghistory_models.Context.objects.count() == 1

    call_command("clear_change_history", "--golden-build")

    # The event table is empty -- not just this row's event, every one.
    assert ZoneEvent.objects.count() == 0
    assert pghistory_models.Context.objects.count() == 0

    # The tracked row itself, and its value, are untouched by the truncate.
    assert Zone.objects.filter(id=zone_id).count() == 1
    assert Zone.objects.get(id=zone_id).name == "Pre-Clear Zone"


@pytest.mark.django_db
def test_golden_build_clears_every_tracked_models_event_table_and_context():
    """Not just the one model exercised above -- every one of the 41 tables.

    Writes a second tracked model in a different app (``core.SiteConfig``,
    which ``track_changes`` limits to a named field list rather than an
    exclude list) so the command is proven to discover tables from the
    registry rather than a table this suite happens to touch first.
    """
    from core.models import SiteConfig, SiteConfigEvent

    zone = ZoneFactory()
    config = SiteConfig.objects.create(agency_name=f"Test Agency {uuid.uuid4()}")

    assert ZoneEvent.objects.filter(pgh_obj_id=zone.id).count() == 1
    assert SiteConfigEvent.objects.filter(pgh_obj_id=config.id).count() == 1

    call_command("clear_change_history", "--golden-build")

    assert ZoneEvent.objects.count() == 0
    assert SiteConfigEvent.objects.count() == 0
    assert pghistory_models.Context.objects.count() == 0

    # Both tracked rows survive with their real values.
    assert Zone.objects.filter(id=zone.id).exists()
    assert SiteConfig.objects.filter(id=config.id).exists()
