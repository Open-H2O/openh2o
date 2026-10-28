# SPDX-License-Identifier: AGPL-3.0-or-later
"""Load OpenH2O's demonstration data into this site.

Runs the whole sequence in ``core/demonstration.py`` in one transaction, so a
load that fails saves nothing. Refuses, before writing anything, when a section
the demonstration needs is switched off or when the site already holds records
of its own. ``remove_demonstration`` takes it out again.

``scripts/rebuild-golden.sh`` builds the demonstration site through this
command, with ``--golden-build`` so that no Site health record is written (the
demonstration site carries none).
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from core import demonstration as demo


class Command(BaseCommand):
    help = (
        "Load the demonstration data (the Merced Subbasin) into this site. "
        "Refuses unless the site holds no records of its own."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--golden-build",
            action="store_true",
            help="Building the demonstration site itself: write no Site health record.",
        )
        parser.add_argument(
            "--record", type=int, default=None,
            help="The Site health record the Demonstration data page made for this run.",
        )
        parser.add_argument(
            "--user", type=int, default=None,
            help="The person who pressed the button on the Demonstration data page.",
        )

    def handle(self, *args, **options):
        run_command("load", self, options)


def run_command(action, command, options):
    """Shared by both commands: lock, record, run, report."""
    user = None
    if options.get("user"):
        user = get_user_model().objects.filter(pk=options["user"]).first()
    golden = options.get("golden_build", False)
    record = options.get("record")

    refusal = None
    if action == "load":
        refusal = demo.load_refusal()
    elif not demo.is_loaded():
        refusal = demo.NOT_LOADED_SENTENCE
    if refusal:
        if record:
            demo.finish_run(record, action, False, refusal)
        raise CommandError(refusal)

    if not demo.try_lock():
        raise CommandError(demo.RUNNING_SENTENCE)
    try:
        if record is None and not golden:
            record = demo.begin_run(action, user)
        try:
            counts = (demo.load if action == "load" else demo.remove)(
                stdout=command.stdout
            )
        except demo.Refused as exc:
            demo.finish_run(record, action, False, str(exc))
            raise CommandError(str(exc)) from None
        except Exception as exc:
            demo.finish_run(record, action, False, demo.failure_sentence(action, exc))
            raise
        done = demo.load_outcome(counts) if action == "load" else demo.remove_outcome(counts)
        demo.finish_run(record, action, True, done, counts)
        command.stdout.write(command.style.SUCCESS(done))
        command.stdout.write(f"{demo.describe(counts)}.")
    finally:
        demo.unlock()
