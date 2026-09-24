# SPDX-License-Identifier: AGPL-3.0-or-later
"""Truncate every pghistory event table (Phase 147, ISS-177).

This exists for exactly one caller: ``scripts/rebuild-golden.sh``, as its last
step before ``pg_dump``. The golden demonstration is meant to look like an
agency that has never touched a knob -- gate 1 and gate 2 of
``verify-candidate.sh`` both pin every pghistory event table (and
``pghistory_context``) at 0 in ``data/demo/expected_shape.json`` -- so whatever
change history the seed commands generated while building the candidate has to
be gone before the dump, or every fresh install would ship with invented
history nobody made.

**This command refuses to run without ``--golden-build``.** On a real
deployment the change history IS the record `core/history.py` exists to keep;
running this there would delete the evidence of who changed what, which is the
one thing Phase 147 was built to stop happening. The flag is not a shortcut
around that -- it is how the golden build says out loud that this is the one
place clearing history is correct.

The table list is derived from the live app registry, the same discipline
``demo_row_counts`` and ``scan_demo_identity`` already use: a concrete, managed
subclass of ``pghistory.models.Event`` that carries a ``pgh_tracked_model`` is
one of the 41 per-model event tables `core/history.py::track_changes`
installs. That filter is also what leaves out pghistory's own
``pghistory.Events`` (an unmanaged union with no table of its own to truncate)
and ``pghistory.MiddlewareEvents`` (a proxy of it) -- neither ``managed`` nor
``proxy`` lets them through. ``pghistory_context`` is added by name because it
is the one pghistory table that is not an ``Event`` subclass at all.

Every table is truncated in a single statement so no ordering assumption is
needed between the event tables and the context table.
"""

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

import pghistory.models as pghistory_models


def _event_tables():
    """The db_table of every real pghistory event table, sorted.

    Excludes ``pghistory.Events`` (unmanaged, no table of its own) and
    ``pghistory.MiddlewareEvents`` (a proxy of it) by construction: neither
    passes the ``managed``/``proxy`` check below, and neither carries a
    ``pgh_tracked_model``.
    """
    tables = []
    for model in apps.get_models():
        if model is pghistory_models.Event or not issubclass(
            model, pghistory_models.Event
        ):
            continue
        meta = model._meta
        if meta.proxy or not meta.managed:
            continue
        if getattr(model, "pgh_tracked_model", None) is None:
            continue
        tables.append(meta.db_table)
    return sorted(tables)


class Command(BaseCommand):
    help = (
        "Truncate every pghistory event table plus pghistory_context. Refuses "
        "unless --golden-build is passed -- on a real deployment the change "
        "history is the record this feature exists to keep."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--golden-build",
            action="store_true",
            help=(
                "Confirm this is building the demonstration golden, not "
                "clearing a real deployment's change history."
            ),
        )

    def handle(self, *args, **options):
        if not options["golden_build"]:
            raise CommandError(
                "clear_change_history refuses to run without --golden-build. "
                "On a real deployment the change history is the record of who "
                "changed what -- clearing it there would delete the exact "
                "evidence Phase 147 exists to keep. This command is meant for "
                "one caller only, scripts/rebuild-golden.sh, building a "
                "demonstration that carries no invented history."
            )

        tables = _event_tables()
        tables.append(pghistory_models.Context._meta.db_table)

        quoted = ", ".join(f'"{table}"' for table in tables)
        with connection.cursor() as cursor:
            cursor.execute(f"TRUNCATE {quoted}")

        self.stdout.write(
            self.style.SUCCESS(
                f"clear_change_history: truncated {len(tables)} tables "
                f"({len(tables) - 1} event tables and pghistory_context)."
            )
        )
