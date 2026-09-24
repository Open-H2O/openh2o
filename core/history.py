# SPDX-License-Identifier: AGPL-3.0-or-later
"""Change history: who changed what, when, and from what (Phase 147, ISS-177).

Every model that holds a figure, or a link that moves one, is decorated with
:func:`track_changes`. The recording is done by Postgres triggers installed by
django-pghistory, not by Django signals, so it catches every way a row can
change: a form save, ``bulk_create``, ``QuerySet.update()``, ``/admin/``, a
management command and raw SQL alike. The calculation engine, the ledger
import, ``attach_orphans_to_period`` and the allocation split all write through
the bulk paths a signal never sees; that is why the choice was triggers
(``147-DISCOVERY.md`` section 7).

**Who did it** is attached as context, never by the code that writes the row:

- a web request: ``pghistory.middleware.HistoryMiddleware`` records the signed-in
  user's id and the request path;
- a management command: ``manage.py`` wraps the whole command in
  :func:`command_context`, so every seed, import and engine run is attributed to
  its command name with no per-command edits;
- a reason: :func:`change_note` adds a free-text note (why) to whatever context
  is already open.

**The policy lives here and nowhere else:**

- inserts, updates AND deletes are recorded (pghistory's default records only
  inserts and updates, which would lose the last values of a removed row), and
  an update is recorded twice, as the row was and as it became;
- geometry columns are never copied into history (GeoDjango support in the
  library is undocumented, and a shape is not a figure);
- ``updated_at`` is never copied, so a save that changes nothing records nothing;
- a foreign key is copied as the plain id of the record it pointed at, not as a
  second foreign key. The history row is a snapshot, not a live reference, and a
  copied foreign key would add a cross-module relation the composition rule
  (``tests/test_composition_rule.py``) has to account for all over again.

Nothing here imports a model at module scope: every app's ``models.py`` imports
this file, including ``core``'s own.
"""

import sys
from contextlib import contextmanager

import pghistory
from django.contrib.gis.db import models as gis_models
from django.db import models

# Commands whose writes are not an operator's: schema work, static files and the
# test runner. The pghistory documentation's own pattern skips the same set.
UNATTRIBUTED_COMMANDS = frozenset(
    {"runserver", "migrate", "makemigrations", "test", "collectstatic", "check"}
)

# The label on the event that records a row as it was just before an update.
LABEL_BEFORE_UPDATE = "before_update"

# Field names never copied into history, on every tracked model.
ALWAYS_EXCLUDED = ("updated_at",)

# The longest note the forms accept.
NOTE_MAX_LENGTH = 500

# The help line under every "Note (why)" box, one wording everywhere.
CHANGE_NOTE_HELP = (
    "Optional. Saved with this change in the change history, which everyone "
    "signed in can read."
)


def _id_column_for(field):
    """A plain integer column standing in for a copied foreign key.

    Same column name as the tracked table's (``parcel_id``), nullable because a
    history row is a snapshot and never re-checked. Always 64-bit: every model
    in this codebase takes the ``BigAutoField`` default key and none sets
    ``to_field`` (the related model cannot be resolved yet when a decorator
    runs, so its key cannot be asked).
    """
    return models.BigIntegerField(
        null=True, blank=True, db_column=field.column, verbose_name=field.verbose_name
    )


def track_changes(*, exclude=(), fields=None):
    """Record every insert, update and delete of the decorated model.

    ``exclude`` names further fields not to copy. ``fields`` instead names the
    only fields to copy (used for ``core.User``, whose password hash and login
    time are not history). Geometry columns and ``updated_at`` are always left
    out; see the module docstring.
    """

    def decorator(model):
        local = [f for f in model._meta.local_fields if f.concrete]
        skip = set(exclude) | set(ALWAYS_EXCLUDED)
        skip |= {f.name for f in local if isinstance(f, gis_models.GeometryField)}
        if fields is not None:
            kept = [name for name in fields if name not in skip]
            chosen = {"fields": kept}
        else:
            kept = [f.name for f in local if f.name not in skip]
            chosen = {"exclude": sorted(skip & {f.name for f in local})}
        attrs = {
            f.name: _id_column_for(f)
            for f in local
            if f.name in kept and isinstance(f, models.ForeignKey)
        }
        return pghistory.track(
            pghistory.InsertEvent(),
            # An update records the row as it was AND as it became, so a
            # change's before value is always the recorded one. Reading it off
            # an earlier event instead would leave the first change to every
            # row that predates tracking (all of a deployment's existing data)
            # with no before at all.
            pghistory.UpdateEvent(LABEL_BEFORE_UPDATE, row="OLD"),
            pghistory.UpdateEvent(),
            pghistory.DeleteEvent(),
            attrs=attrs,
            **chosen,
        )(model)

    return decorator


def _setup_django_from_argv(argv):
    """Load settings and the app registry before a history context opens.

    Opening a context touches the database connection, and the PostGIS backend
    imports models as it loads, so both have to be ready first. Django normally
    applies ``--settings`` / ``--pythonpath`` and calls ``django.setup()``
    inside ``execute_from_command_line``; this does the same two steps the way
    Django's own ``ManagementUtility.execute`` does (``setup()`` is idempotent,
    so the second call there is a no-op).
    """
    import django
    from django.core.management.base import CommandParser, handle_default_options

    parser = CommandParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--settings")
    parser.add_argument("--pythonpath")
    parser.add_argument("args", nargs="*")
    try:
        options, _ = parser.parse_known_args(argv[2:])
    except Exception:  # noqa: BLE001 - Django re-parses and reports it properly
        return
    handle_default_options(options)
    django.setup()


@contextmanager
def command_context(argv=None):
    """Attribute every change a management command makes to that command.

    Used by ``manage.py`` around ``execute_from_command_line``. A command in
    :data:`UNATTRIBUTED_COMMANDS`, or no command at all, runs with no context.
    Scripts that call ``call_command`` from Python can use it the same way.
    """
    argv = list(sys.argv if argv is None else argv)
    name = argv[1] if len(argv) > 1 else ""
    if not name or name.startswith("-") or name in UNATTRIBUTED_COMMANDS:
        yield
        return
    _setup_django_from_argv(argv)
    with pghistory.context(command=name, argv=argv[1:]):
        yield


def clean_note(text):
    """A submitted note as stored: stripped, capped, or None when empty."""
    text = (text or "").strip()
    return text[:NOTE_MAX_LENGTH] or None


@contextmanager
def change_note(text):
    """Attach a note (why) to every change made inside the block.

    An empty note attaches nothing. The note joins whatever context is already
    open (the request's, or the command's), so the change keeps its person.
    """
    note = clean_note(text)
    if note is None:
        yield
        return
    with pghistory.context(note=note):
        yield
